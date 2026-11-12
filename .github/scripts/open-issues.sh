#!/usr/bin/env bash
# open-issues.sh: convierte los informes de seguridad en issues de GitHub: uno por paquete+versión
# (todos sus CVE juntos) y uno por secreto.
#
# Uso: open-issues.sh [--dry-run] [--repo OWNER/REPO] [--run-url URL] [--max-new N] <informe.json>...
#
# Informes admitidos (el tipo y la carpeta salen del nombre: `<tipo>--<carpeta>.json`, con `__`
# por `/` y `root` para la raíz): npm-audit, npm-audit-dev, pip-audit, pip-audit-dev (salida
# JSON de `npm audit` y `pip-audit`), trivy* (`trivy ... -f json`) y gitleaks* (informe JSON).
# Requiere bash >= 4, jq y, sin --dry-run, gh (con GH_TOKEN) y permiso `issues: write`.
#
# Por paquete+versión+objetivo: título `[gravedad máxima] paquete@versión: N CVE (corregido en X)`
# (o `Secreto detectado: regla en fichero`), etiquetas `security`, `sev:*` y `sla:*` (plazo de la
# gravedad máxima), cuerpo con la tabla de CVE, la solución y los pasos. Una marca oculta
# `fp=<huella> src=<fuente> v=2 ids=<hash de los IDs>` evita duplicados: la huella NO incluye los IDs,
# así los CVE nuevos del mismo paquete+versión no abren otro issue; cuando cambia la lista de IDs
# se comenta una vez con los nuevos. Si el issue abierto existe y el plazo nuevo es más estricto,
# sube sus etiquetas; si el paquete ya no aparece en su informe, comenta una vez (NUNCA cierra:
# cerrar lo decide una persona al publicar el arreglo). Los issues antiguos (un issue por CVE,
# marca sin `v=`) se tratan como legado: no reciben ese comentario y se avisa de que hay que
# cerrarlos a mano. Los informes son datos no confiables: los textos
# se limpian (sin saltos de línea, comillas invertidas ni etiquetas HTML) y el valor de un secreto
# o su contexto no se leen nunca.
# Entorno: SLA_CRITICAL_HIGH_HOURS (48), SLA_MODERATE (next-release), SLA_LOW (monthly),
#   GITHUB_REPOSITORY (valor por defecto de --repo), OPEN_ISSUES_NOW (epoch fijo, para pruebas).
# Salida: 0 bien (también con avisos), 1 error (informe ilegible o fallo de gh), 2 uso incorrecto.
set -uo pipefail

usage() {
  echo "Uso: $(basename "$0") [--dry-run] [--repo OWNER/REPO] [--run-url URL] [--max-new N] <informe.json>..." >&2
  exit 2
}
warn() { echo "Aviso: $*" >&2; }
err() {
  echo "Error: $*" >&2
  ERRORS=$((ERRORS + 1))
}

if [ "${BASH_VERSINFO[0]}" -lt 4 ]; then
  echo "Hace falta bash >= 4." >&2
  exit 2
fi

DRY=0
REPO="${GITHUB_REPOSITORY:-}"
RUN_URL=""
MAX_NEW=10
FILES=()
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY=1
      shift
      ;;
    --repo)
      [ $# -ge 2 ] || usage
      REPO="$2"
      shift 2
      ;;
    --run-url)
      [ $# -ge 2 ] || usage
      RUN_URL="$2"
      shift 2
      ;;
    --max-new)
      [ $# -ge 2 ] || usage
      MAX_NEW="$2"
      shift 2
      ;;
    -h | --help) usage ;;
    -*)
      echo "Opción desconocida: $1" >&2
      usage
      ;;
    *)
      FILES+=("$1")
      shift
      ;;
  esac
done
[ "${#FILES[@]}" -gt 0 ] || usage
grep -Eq '^[0-9]+$' <<<"$MAX_NEW" || {
  echo "--max-new debe ser un entero." >&2
  exit 2
}
command -v jq >/dev/null 2>&1 || {
  echo "Falta jq." >&2
  exit 2
}
if [ "$DRY" -eq 0 ]; then
  command -v gh >/dev/null 2>&1 || {
    echo "Falta gh." >&2
    exit 2
  }
  grep -Eq '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$' <<<"$REPO" || {
    echo "Indica el repositorio con --repo OWNER/REPO (o GITHUB_REPOSITORY)." >&2
    exit 2
  }
fi
if [ -n "$RUN_URL" ] && ! grep -Eq '^https?://[A-Za-z0-9._~:/?#@!$&()*+,;=%-]+$' <<<"$RUN_URL"; then
  warn "--run-url no es una URL segura; se ignora."
  RUN_URL=""
fi

# --- plazos ---------------------------------------------------------------------------------------
HOURS="${SLA_CRITICAL_HIGH_HOURS:-48}"
grep -Eq '^[1-9][0-9]{0,3}$' <<<"$HOURS" || HOURS=48
SLA_MOD="${SLA_MODERATE:-next-release}"
grep -Eq '^[A-Za-z0-9._-]{1,40}$' <<<"$SLA_MOD" || SLA_MOD=next-release
SLA_LOW_V="${SLA_LOW:-monthly}"
grep -Eq '^[A-Za-z0-9._-]{1,40}$' <<<"$SLA_LOW_V" || SLA_LOW_V=monthly
NOW="${OPEN_ISSUES_NOW:-}"
grep -Eq '^[0-9]{1,12}$' <<<"$NOW" || NOW="$(date +%s)"

# --- normalización (jq) -----------------------------------------------------------------------------
# Entrada: el informe. Variables: kind (npm|pip|trivy|gitleaks), scope, fam, srcname, pathtext,
# path, hours, mod, low, now, run. Salida: un objeto JSON por hallazgo.
read -r -d '' JQ_PROGRAM <<'JQ' || true
def clean($n): (. // "" | tostring
  | gsub("[\u0001-\u001f\u007f]"; " ")
  | gsub("`"; "")
  | gsub("<(?=[A-Za-z/!?])"; "‹")
  | gsub("\\s+"; " ") | sub("^ "; "") | sub(" $"; "") | .[0:$n]);
def code: "`\(.)`";
def normsev: (. // "" | tostring | ascii_downcase) as $s
  | if $s == "critical" then {sev: "critical", assumed: false}
    elif $s == "high" then {sev: "high", assumed: false}
    elif ($s == "moderate" or $s == "medium") then {sev: "moderate", assumed: false}
    elif ($s == "low" or $s == "info") then {sev: "low", assumed: false}
    else {sev: "moderate", assumed: true} end;
def sla($sev; $sc):
  if $sc == "secret" then {label: "sla:immediate", rank: 0, text: "inmediato (rotar ahora)"}
  elif ($sc == "production" and ($sev == "critical" or $sev == "high")) then
    {label: "sla:\($hours)h", rank: 1,
     text: "\($hours) horas (límite: \(($now + $hours * 3600) | strftime("%Y-%m-%d %H:%M UTC")))"}
  elif ($sc == "production" and $sev == "moderate") then {label: "sla:\($mod)", rank: 2, text: $mod}
  else {label: "sla:\($low)", rank: 3, text: $low} end;

def raw:
  if $kind == "npm" then
    [ (.vulnerabilities // {}) | to_entries[] | .value as $v | ($v.via // [])[] | select(type == "object")
      | {id: ((.url // "") | split("/") | last | if . == "" then (.source | tostring) else . end),
         package: .name, version: (.range // ""), severity: .severity, title: .title,
         fix: ($v.fixAvailable | if type == "object" then "\(.name)@\(.version)" elif . == true then "disponible (npm audit fix)" else "" end),
         target: "", eco: "npm", kver: ""} ]
    | unique_by([.id, .package])
  elif $kind == "pip" then
    [ (if type == "array" then . else (.dependencies // []) end)[] | . as $d | ($d.vulns // [])[]
      | {id: .id, package: $d.name, version: $d.version, severity: "", title: (.description // ""),
         fix: ((.fix_versions // []) | join(", ")), target: "", eco: "pip", kver: $d.version} ]
  elif $kind == "trivy" then
    [ (.Results // [])[] | (.Target // "") as $t | (.Type // "") as $ty | (.Vulnerabilities // [])[]
      | {id: .VulnerabilityID, package: .PkgName, version: .InstalledVersion, severity: .Severity,
         title: (.Title // ""), fix: (.FixedVersion // ""), target: $t, eco: ($ty | ascii_downcase),
         kver: .InstalledVersion} ]
  else
    [ .[] | {id: .RuleID, file: .File, line: (.StartLine // 0), commit: ((.Commit // "") | .[0:8]),
             fingerprint: (.Fingerprint // "\(.File):\(.RuleID):\(.StartLine)")} ]
  end;

def sevrank: {"critical": 0, "high": 1, "moderate": 2, "low": 3}[.];
def vkey: split("[.+~:_-]"; "g") | map(tonumber? // .);
# La versión corregida mayor de una lista (cada elemento puede ser "a, b").
def maxfix: [.[] | split(", ")[] | select(. != "")] | unique | sort_by(vkey) | last // "";
def cell: gsub("[|]"; "/");
def pkgsafe: test("^[A-Za-z0-9._+@/-]+$");
def versafe: test("^[A-Za-z0-9._+:~-]+$");
def solution($eco; $pkg; $fix):
  if $fix == "" then "sin solución conocida: documenta la mitigación y la fecha de revisión"
  elif $eco == "npm" and ($fix | test("^[A-Za-z0-9._+@/-]+@[A-Za-z0-9._+~-]+$")) then
    "actualizar a \($fix | code) (`npm install \($fix)`)"
  elif $eco == "npm" then "actualizar a la versión que corrige (`npm audit fix`; revisa los cambios mayores)"
  elif ($pkg | pkgsafe) and ($fix | versafe) then
    "actualizar \($pkg | code) a >= \($fix | code)" +
    (if $eco == "alpine" then " (`apk upgrade \($pkg)`, o reconstruye la imagen con una base más reciente)"
     elif ($eco == "debian" or $eco == "ubuntu") then " (`apt-get install --only-upgrade \($pkg)`, o reconstruye la imagen con una base más reciente)"
     elif ($eco == "pip" or $eco == "python-pkg" or $eco == "poetry" or $eco == "pipenv" or $eco == "uv") then " (`pip install -U '\($pkg)>=\($fix)'`)"
     elif ($eco == "yarn" or $eco == "pnpm" or $eco == "node-pkg") then " (`npm install \($pkg)@\($fix)`)"
     else " con el gestor de paquetes del ecosistema" end)
  else "actualizar el paquete a la versión que corrige (\($fix | code))" end;

# Agrupa por paquete + versión instalada + objetivo: un objeto por grupo con sus CVE ordenados
# por gravedad (y luego por ID), la gravedad máxima y la versión corregida mayor.
def groups:
  raw
  | map(. + {pkgc: (.package | clean(100)), verc: (.version | clean(60)), idc: (.id | clean(60)),
             ns: (.severity | normsev), fixc: (.fix | clean(120)), kverc: (.kver | clean(60))})
  | group_by([.pkgc, .kverc, .target])
  | map(
      (map({id: .idc, sev: .ns.sev, assumed: .ns.assumed, fix: .fixc, title: .title,
            r: (.ns.sev | sevrank)}) | unique_by(.id) | sort_by([.r, .id])) as $c
      | {pkg: .[0].pkgc, kver: .[0].kverc, target: .[0].target, eco: .[0].eco,
         ver: ([.[].verc] | map(select(. != "")) | unique | join(", ")),
         cves: $c, sev: $c[0].sev, assumed: ($c | all(.assumed)),
         fix: ([$c[].fix] | maxfix), top: ($c[0].title | clean(300))});

(if $kind == "gitleaks" then raw else groups end)[] |
  if $kind == "gitleaks" then
    (.id | clean(80)) as $rule | (.file | clean(200)) as $file
    | sla("critical"; "secret") as $s
    | {title: "Secreto detectado: \($rule) en \($file)",
       sev: "critical", rank: $s.rank, slalabel: $s.label,
       keyraw: "gitleaks|\($path)|\(.fingerprint | tostring)|",
       src: "\($srcname):\($path)",
       body: ([
         "## Secreto detectado", "",
         "**ROTA la credencial ahora**, antes de limpiar nada: un secreto que llegó a un remoto se considera expuesto. Este issue no incluye el valor.", "",
         "- **Regla**: \($rule | code)",
         "- **Fichero**: \($file | code) (línea \(.line | tostring | clean(10)))",
         "- **Commit**: \(.commit | clean(8) | code)",
         "- **Plazo**: \($s.text)"
       ] + (if $run != "" then ["- **Detectado en**: \($run)"] else [] end) + [
         "", "## Pasos", "",
         "1. Rota la credencial en el servicio emisor.",
         "2. Revisa los registros de uso del servicio por si se abusó de ella.",
         "3. Quita el secreto del código y usa una variable de entorno o un gestor de secretos; añade el fichero al ignorado.",
         "4. Limpiar el historial es opcional y nunca sustituye a rotar.",
         "5. Cierra este issue tras rotar."
       ] | join("\n"))}
  else
    .pkg as $pkg | .ver as $ver | .sev as $sev | .fix as $fix | (.cves | length) as $n
    | sla($sev; $scope) as $s
    | {title: ("[\($sev)] \($pkg)\(if $ver != "" then "@\($ver)" else "" end): \($n) CVE\(if $fix != "" then " (corregido en \($fix))" else "" end)" | .[0:250]),
       sev: $sev, rank: $s.rank, slalabel: $s.label,
       ids: [.cves[].id],
       cves: (.cves | map({id, sev, fix})),
       keyraw: "\($fam)|\($path)|\(.target)|\($pkg)|\(.kver)",
       src: "\($srcname):\($path)",
       body: ([
         "## Hallazgo de seguridad", "",
         "- **Origen**: \($fam | code) (carpeta \($pathtext | code))",
         "- **Paquete**: \($pkg | code)",
         "- **Versión o rango afectado**: \(if $ver == "" then "no informada" else ($ver | code) end)",
         "- **Vulnerabilidades**: \($n)",
         "- **Gravedad máxima**: \($sev)\(if .assumed then " (la herramienta no informa la gravedad: se trata como moderate)" else "" end)",
         "- **Ámbito**: \(if $scope == "production" then "producción" else "desarrollo" end)",
         "- **Plazo**: \($s.text) (según la gravedad máxima)",
         "- **Solución**: \(solution(.eco; $pkg; $fix))"
       ] + (if .top != "" then ["- **Descripción de la más grave**: \(.top | code)"] else [] end)
         + (if (.target | clean(200)) != "" then ["- **Objetivo analizado**: \(.target | clean(200) | code)"] else [] end)
         + (if $run != "" then ["- **Detectado en**: \($run)"] else [] end) + [
         "", "## Vulnerabilidades", "",
         "| ID | Gravedad | Corregido en |", "|---|---|---|"
       ] + (.cves[0:100] | map("| \(.id | cell | code) | \(.sev) | \(if .fix == "" then "sin solución conocida" else (.fix | cell | code) end) |"))
         + (if $n > 100 then ["", "(y \($n - 100) más; la lista completa está en el informe)"] else [] end) + [
         "", "## Pasos", "",
         "1. Actualiza la dependencia al mínimo parcheado; si no hay parche, documenta la mitigación y la fecha de revisión.",
         "2. Publica el arreglo con el flujo normal de versiones.",
         "3. Cierra este issue tras publicar, con el comentario «Publicado en vX.Y.Z».", "",
         "Los plazos son valores por defecto del proceso de seguridad del repositorio."
       ] | join("\n"))}
  end
JQ

# Comprobación de estructura mínima por tipo.
read -r -d '' JQ_VALID_npm <<'JQ' || true
type == "object" and has("vulnerabilities")
JQ
read -r -d '' JQ_VALID_pip <<'JQ' || true
type == "array" or (type == "object" and has("dependencies"))
JQ
read -r -d '' JQ_VALID_trivy <<'JQ' || true
type == "object" and (has("Results") or has("SchemaVersion"))
JQ
read -r -d '' JQ_VALID_gitleaks <<'JQ' || true
type == "array"
JQ

# --- estado -----------------------------------------------------------------------------------------
ERRORS=0
TOTAL=0
CREATED=0
EXISTING=0
UPDATED=0
RESOLVED=0
NEWIDS=0
LEGACY=0
SKIPPED_LIMIT=0
declare -A OPEN_NUM=() OPEN_LABELS=() OPEN_SRC=() OPEN_V=() OPEN_IDS=() CUR=() SRC_SEEN=() LABEL_DONE=()
BODY_FILE="$(mktemp)"
trap 'rm -f "$BODY_FILE"' EXIT

ghc() { gh "$@"; }

ensure_label() {
  local name="$1" color desc
  [ "$DRY" -eq 1 ] && return 0
  [ -n "${LABEL_DONE[$name]:-}" ] && return 0
  case "$name" in
    security) color="b60205"; desc="Hallazgo de seguridad" ;;
    sev:critical) color="b60205"; desc="Gravedad crítica" ;;
    sev:high) color="d93f0b"; desc="Gravedad alta" ;;
    sev:moderate) color="fbca04"; desc="Gravedad moderada" ;;
    sev:low) color="0e8a16"; desc="Gravedad baja" ;;
    *) color="5319e7"; desc="Plazo de resolución" ;;
  esac
  ghc label create "$name" --repo "$REPO" --color "$color" --description "$desc" --force >/dev/null 2>&1 || warn "no se pudo asegurar la etiqueta $name"
  LABEL_DONE[$name]=1
}

rank_of_label() { # etiqueta sla:* -> rango, o vacío si no se reconoce
  case "$1" in
    sla:immediate) echo 0 ;;
    "sla:${HOURS}h") echo 1 ;;
    "sla:${SLA_MOD}") echo 2 ;;
    "sla:${SLA_LOW_V}") echo 3 ;;
    *) echo "" ;;
  esac
}

# --- issues abiertos ----------------------------------------------------------------------------------
if [ "$DRY" -eq 0 ]; then
  if issues_json="$(ghc issue list --repo "$REPO" --state open --label security --limit 1000 --json number,body,labels)"; then
    # Campos vacíos como "-" (el tabulador es espacio en blanco para read y colapsaría los vacíos).
    while IFS=$'\t' read -r num fp src v ids labels; do
      [ -n "$fp" ] || continue
      OPEN_NUM[$fp]="$num"
      OPEN_SRC[$fp]="$src"
      [ "$v" = "-" ] && v=""
      [ "$ids" = "-" ] && ids=""
      OPEN_V[$fp]="$v"
      OPEN_IDS[$fp]="$ids"
      OPEN_LABELS[$fp]="$labels"
    done < <(printf '%s' "$issues_json" | jq -r '.[] | . as $i
      | ($i.body // "" | [match("<!-- repo-warden:fp=([0-9a-f]{16}) src=([A-Za-z0-9._:/-]+)( v=([0-9]+))?( ids=([0-9a-f]{16}))? -->"; "g")] | last) as $m
      | select($m != null)
      | [$i.number, $m.captures[0].string, $m.captures[1].string, ($m.captures[3].string // "-"), ($m.captures[5].string // "-"),
         (([$i.labels[]?.name] | join(",")) | if . == "" then "-" else . end)] | @tsv' 2>/dev/null)
  else
    err "no se pudo listar los issues abiertos"
  fi
fi

# Comenta en un issue existente los CVE del hallazgo que ni su cuerpo ni sus comentarios mencionan
# todavía (así cada cambio se comunica una sola vez). Nunca edita ni cierra.
notify_new_ids() { # $1 = número, $2 = JSON del hallazgo
  local num="$1" f="$2" view added
  if ! view="$(ghc issue view "$num" --repo "$REPO" --json body,comments 2>/dev/null)"; then
    warn "no se pudo leer el issue #$num para comprobar los CVE nuevos"
    return 0
  fi
  added="$(jq -rn --argjson view "$view" --argjson f "$f" --arg run "$RUN_URL" '
    ([$view.body // ""] + [$view.comments[]?.body // ""] | join("\n")
      | [scan("[A-Za-z0-9_.:-]+") | sub("[.:-]+$"; "")]) as $seen
    | [$f.cves[] | select(.id as $i | $seen | index($i) | not)] as $new
    | if ($new | length) == 0 then empty else
      ([ "Desde la última ejecución\(if $run != "" then " (\($run))" else "" end) aparecen \($new | length) CVE nuevos del mismo paquete y versión (no se edita el cuerpo del issue):", "",
         "| ID | Gravedad | Corregido en |", "|---|---|---|" ]
       + ($new[0:100] | map("| `\(.id | gsub("[|`]"; "/"))` | \(.sev) | \(if .fix == "" then "sin solución conocida" else "`\(.fix | gsub("[|`]"; "/"))`" end) |"))
       + (if ($new | length) > 100 then ["", "(y \(($new | length) - 100) más)"] else [] end)
       | join("\n")) end' 2>/dev/null)"
  [ -n "$added" ] || return 0
  printf '%s\n' "$added" >"$BODY_FILE"
  if ghc issue comment "$num" --repo "$REPO" --body-file "$BODY_FILE" >/dev/null; then
    NEWIDS=$((NEWIDS + 1))
  else
    err "no se pudo comentar el issue #$num"
  fi
}

# --- procesar informes ------------------------------------------------------------------------------------
process_finding() { # $1 = JSON del hallazgo
  local f="$1" title body sev rank slalabel src keyraw fp labels idshash
  title="$(jq -r '.title' <<<"$f")"
  sev="$(jq -r '.sev' <<<"$f")"
  rank="$(jq -r '.rank' <<<"$f")"
  slalabel="$(jq -r '.slalabel' <<<"$f")"
  src="$(jq -r '.src' <<<"$f")"
  keyraw="$(jq -r '.keyraw' <<<"$f")"
  body="$(jq -r '.body' <<<"$f")"
  fp="$(printf '%s' "$keyraw" | sha256sum | cut -c1-16)"
  idshash=""
  if [ "$(jq -r '(.ids // []) | length' <<<"$f")" -gt 0 ]; then
    idshash="$(jq -r '.ids[]' <<<"$f" | LC_ALL=C sort -u | sha256sum | cut -c1-16)"
  fi
  CUR[$fp]=1
  TOTAL=$((TOTAL + 1))

  if [ -n "${OPEN_NUM[$fp]:-}" ]; then
    EXISTING=$((EXISTING + 1))
    local num="${OPEN_NUM[$fp]}" old oldrank="" l unknown=0
    local -a old_sla=() old_sev=() add=() remove=()
    IFS=',' read -r -a old <<<"${OPEN_LABELS[$fp]:-}"
    for l in "${old[@]:-}"; do
      case "$l" in
        sla:*)
          old_sla+=("$l")
          local r
          r="$(rank_of_label "$l")"
          if [ -z "$r" ]; then unknown=1; elif [ -z "$oldrank" ] || [ "$r" -lt "$oldrank" ]; then oldrank="$r"; fi
          ;;
        sev:*) old_sev+=("$l") ;;
      esac
    done
    if [ "$unknown" -eq 0 ] && [ -n "$oldrank" ] && [ "$rank" -lt "$oldrank" ]; then
      for l in "${old_sla[@]}"; do [ "$l" = "$slalabel" ] || remove+=("$l"); done
      for l in "${old_sev[@]:-}"; do [ -z "$l" ] || [ "$l" = "sev:$sev" ] || remove+=("$l"); done
      add+=("$slalabel")
      grep -qx "sev:$sev" <<<"$(printf '%s\n' "${old[@]:-}")" || add+=("sev:$sev")
      if [ "$DRY" -eq 1 ]; then
        echo "ACTUALIZARÍA #$num: $slalabel (gravedad $sev)"
      else
        local a
        for a in "${add[@]}"; do ensure_label "$a"; done
        local -a cmd=(issue edit "$num" --repo "$REPO" --add-label "$(IFS=,; echo "${add[*]}")")
        [ "${#remove[@]}" -eq 0 ] || cmd+=(--remove-label "$(IFS=,; echo "${remove[*]}")")
        if ghc "${cmd[@]}" >/dev/null; then
          {
            echo "Una ejecución posterior${RUN_URL:+ ($RUN_URL)} ve este hallazgo con un plazo más estricto: etiquetas actualizadas a \`$slalabel\` y \`sev:$sev\`."
          } >"$BODY_FILE"
          ghc issue comment "$num" --repo "$REPO" --body-file "$BODY_FILE" >/dev/null || err "no se pudo comentar el issue #$num"
          UPDATED=$((UPDATED + 1))
          OPEN_LABELS[$fp]="security,sev:$sev,$slalabel"
        else
          err "no se pudo actualizar las etiquetas del issue #$num"
        fi
      fi
    fi
    if [ "$DRY" -eq 0 ] && [ -n "$idshash" ] && [ -n "${OPEN_IDS[$fp]:-}" ] && [ "${OPEN_IDS[$fp]}" != "$idshash" ]; then
      notify_new_ids "$num" "$f"
    fi
    return 0
  fi

  if [ "$CREATED" -ge "$MAX_NEW" ]; then
    SKIPPED_LIMIT=$((SKIPPED_LIMIT + 1))
    return 0
  fi
  labels=(security "sev:$sev" "$slalabel")
  if [ "$DRY" -eq 1 ]; then
    echo "CREARÍA: $title (${labels[*]})"
    CREATED=$((CREATED + 1))
    OPEN_NUM[$fp]="dry"
    OPEN_LABELS[$fp]="security,sev:$sev,$slalabel"
    return 0
  fi
  printf '%s\n<!-- repo-warden:fp=%s src=%s v=2%s -->\n' "$body" "$fp" "$src" "${idshash:+ ids=$idshash}" >"$BODY_FILE"
  local l url
  for l in "${labels[@]}"; do ensure_label "$l"; done
  local -a cmd=(issue create --repo "$REPO" --title "$title" --body-file "$BODY_FILE")
  for l in "${labels[@]}"; do cmd+=(--label "$l"); done
  if url="$(ghc "${cmd[@]}")"; then
    CREATED=$((CREATED + 1))
    echo "creado: $title ${url##*$'\n'}"
    OPEN_NUM[$fp]="${url##*/}"
    OPEN_SRC[$fp]="$src"
    OPEN_LABELS[$fp]="security,sev:$sev,$slalabel"
  else
    err "no se pudo crear el issue: $title"
  fi
}

for file in "${FILES[@]}"; do
  base="$(basename "$file")"
  case "$base" in
    npm-audit-dev--* | npm-audit-dev.json) kind=npm; fam=npm-audit; srcname=npm-audit-dev; scope=development ;;
    npm-audit--* | npm-audit.json) kind=npm; fam=npm-audit; srcname=npm-audit; scope=production ;;
    pip-audit-dev--* | pip-audit-dev.json) kind=pip; fam=pip-audit; srcname=pip-audit-dev; scope=development ;;
    pip-audit--* | pip-audit.json) kind=pip; fam=pip-audit; srcname=pip-audit; scope=production ;;
    gitleaks*) kind=gitleaks; fam=gitleaks; srcname=gitleaks; scope=secret ;;
    trivy*) kind=trivy; fam=trivy; srcname=trivy; scope=production ;;
    *)
      warn "nombre de informe desconocido, se omite: $base"
      continue
      ;;
  esac
  slug="root"
  case "$base" in *--*)
    slug="${base#*--}"
    slug="${slug%.json}"
    ;;
  esac
  if ! grep -Eq '^[A-Za-z0-9._-]+(__[A-Za-z0-9._-]+)*$' <<<"$slug"; then
    warn "carpeta no admitida en el nombre del informe, se omite: $base"
    continue
  fi
  path="${slug//__//}"
  if [ "$path" = "root" ]; then pathtext="raíz del repositorio"; else pathtext="$path"; fi

  if [ ! -r "$file" ] || ! jq -e . "$file" >/dev/null 2>&1; then
    err "JSON inválido o ilegible: $base"
    continue
  fi
  validvar="JQ_VALID_$kind"
  if ! jq -e "${!validvar}" "$file" >/dev/null 2>&1; then
    warn "informe de $base sin la estructura esperada (no reconocido); se omite y no se cierra nada por él."
    continue
  fi
  SRC_SEEN["$srcname:$path"]=1
  if ! out="$(jq -c --arg kind "$kind" --arg scope "$scope" --arg fam "$fam" --arg srcname "$srcname" \
    --arg pathtext "$pathtext" --arg path "$path" --argjson hours "$HOURS" --arg mod "$SLA_MOD" \
    --arg low "$SLA_LOW_V" --argjson now "$NOW" --arg run "$RUN_URL" "$JQ_PROGRAM" "$file" 2>&1)"; then
    err "no se pudo leer $base: ${out:0:200}"
    continue
  fi
  while IFS= read -r finding; do
    [ -n "$finding" ] || continue
    process_finding "$finding"
  done <<<"$out"
done

# --- hallazgos que ya no aparecen -------------------------------------------------------------------------
if [ "$DRY" -eq 0 ]; then
  for fp in "${!OPEN_SRC[@]}"; do
    [ -z "${CUR[$fp]:-}" ] || continue
    [ -n "${SRC_SEEN[${OPEN_SRC[$fp]}]:-}" ] || continue
    num="${OPEN_NUM[$fp]}"
    grep -Eq '^[0-9]+$' <<<"$num" || continue
    # Formato antiguo (un issue por CVE, marca sin v=): su huella ya no se genera, así que "ya no
    # aparece" sería engañoso. Los secretos conservan la huella y siguen el flujo normal.
    if [ -z "${OPEN_V[$fp]:-}" ] && [ "${OPEN_SRC[$fp]%%:*}" != "gitleaks" ]; then
      LEGACY=$((LEGACY + 1))
      continue
    fi
    if comments_json="$(ghc issue view "$num" --repo "$REPO" --json comments 2>/dev/null)" &&
      jq -e 'any(.comments[]?; (.body // "") | contains("<!-- repo-warden:resolved -->"))' <<<"$comments_json" >/dev/null 2>&1; then
      continue
    fi
    {
      echo "Este hallazgo ya no aparece en el último informe de \`${OPEN_SRC[$fp]}\`${RUN_URL:+ ($RUN_URL)}. Si ya está arreglado, confírmalo y cierra el issue tras publicar la corrección; si no, comprueba que la auditoría se ejecutó entera."
      echo "<!-- repo-warden:resolved -->"
    } >"$BODY_FILE"
    if ghc issue comment "$num" --repo "$REPO" --body-file "$BODY_FILE" >/dev/null; then
      RESOLVED=$((RESOLVED + 1))
    else
      err "no se pudo comentar el issue #$num"
    fi
  done
fi

if [ "$SKIPPED_LIMIT" -gt 0 ]; then
  warn "límite de $MAX_NEW issues nuevos por ejecución: $SKIPPED_LIMIT hallazgos sin crear (se crearán en las siguientes ejecuciones)."
fi
if [ "$LEGACY" -gt 0 ]; then
  warn "$LEGACY issues abiertos con formato antiguo (uno por CVE, marca sin v=): no se comentan; ciérralos a mano cuando revises el informe nuevo (un issue por paquete+versión)."
fi
echo "Resumen: $TOTAL hallazgos, $CREATED creados, $EXISTING existentes, $UPDATED con plazo actualizado, $NEWIDS con CVE nuevos comentados, $RESOLVED con aviso de resuelto, $SKIPPED_LIMIT sin crear por el límite."
[ "$ERRORS" -eq 0 ] || exit 1
exit 0
