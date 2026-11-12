#!/usr/bin/env bash
# open-issues.sh: convierte los informes de seguridad en issues de GitHub, uno por hallazgo.
#
# Uso: open-issues.sh [--dry-run] [--repo OWNER/REPO] [--run-url URL] [--max-new N] <informe.json>...
#
# Informes admitidos (el tipo y la carpeta salen del nombre: `<tipo>--<carpeta>.json`, con `__`
# por `/` y `root` para la raíz): npm-audit, npm-audit-dev, pip-audit, pip-audit-dev (salida
# JSON de `npm audit` y `pip-audit`), trivy* (`trivy ... -f json`) y gitleaks* (informe JSON).
# Requiere bash >= 4, jq y, sin --dry-run, gh (con GH_TOKEN) y permiso `issues: write`.
#
# Por hallazgo: título `[gravedad] paquete@versión: ID` (o `Secreto detectado: regla en fichero`),
# etiquetas `security`, `sev:*` y `sla:*`, cuerpo con plazo y pasos. Una marca oculta con la huella
# del hallazgo evita duplicados; si el issue abierto existe y el plazo nuevo es más estricto, sube
# sus etiquetas; si el hallazgo ya no aparece en su informe, comenta una vez (NUNCA cierra: cerrar
# lo decide una persona al publicar el arreglo). Los informes son datos no confiables: los textos
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
MAX_NEW=25
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
         target: ""} ]
    | unique_by([.id, .package])
  elif $kind == "pip" then
    [ (if type == "array" then . else (.dependencies // []) end)[] | . as $d | ($d.vulns // [])[]
      | {id: .id, package: $d.name, version: $d.version, severity: "", title: (.description // ""),
         fix: ((.fix_versions // []) | join(", ")), target: ""} ]
  elif $kind == "trivy" then
    [ (.Results // [])[] | (.Target // "") as $t | (.Vulnerabilities // [])[]
      | {id: .VulnerabilityID, package: .PkgName, version: .InstalledVersion, severity: .Severity,
         title: (.Title // ""), fix: (.FixedVersion // ""), target: $t} ]
  else
    [ .[] | {id: .RuleID, file: .File, line: (.StartLine // 0), commit: ((.Commit // "") | .[0:8]),
             fingerprint: (.Fingerprint // "\(.File):\(.RuleID):\(.StartLine)")} ]
  end;

raw[] |
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
    (.id | clean(60)) as $id | (.package | clean(100)) as $pkg | (.version | clean(60)) as $ver
    | (.severity | normsev) as $ns
    | sla($ns.sev; $scope) as $s
    | {title: "[\($ns.sev)] \($pkg)\(if $ver != "" then "@\($ver)" else "" end): \($id)",
       sev: $ns.sev, rank: $s.rank, slalabel: $s.label,
       keyraw: "\($fam)|\($path)|\(.target)|\($id)|\($pkg)",
       src: "\($srcname):\($path)",
       body: ([
         "## Hallazgo de seguridad", "",
         "- **Origen**: \($fam | code) (carpeta \($pathtext | code))",
         "- **Paquete**: \($pkg | code)",
         "- **Versión o rango afectado**: \(if $ver == "" then "no informada" else ($ver | code) end)",
         "- **Identificador**: \($id | code)",
         "- **Gravedad**: \($ns.sev)\(if $ns.assumed then " (la herramienta no informa la gravedad: se trata como moderate)" else "" end)",
         "- **Ámbito**: \(if $scope == "production" then "producción" else "desarrollo" end)",
         "- **Plazo**: \($s.text)",
         "- **Solución**: \(if (.fix | clean(120)) == "" then "sin solución conocida" else (.fix | clean(120) | code) end)"
       ] + (if (.title | clean(300)) != "" then ["- **Descripción**: \(.title | clean(300) | code)"] else [] end)
         + (if (.target | clean(200)) != "" then ["- **Objetivo analizado**: \(.target | clean(200) | code)"] else [] end)
         + (if $run != "" then ["- **Detectado en**: \($run)"] else [] end) + [
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
SKIPPED_LIMIT=0
declare -A OPEN_NUM=() OPEN_LABELS=() OPEN_SRC=() CUR=() SRC_SEEN=() LABEL_DONE=()
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
    while IFS=$'\t' read -r num fp src labels; do
      [ -n "$fp" ] || continue
      OPEN_NUM[$fp]="$num"
      OPEN_SRC[$fp]="$src"
      OPEN_LABELS[$fp]="$labels"
    done < <(printf '%s' "$issues_json" | jq -r '.[] | . as $i
      | ($i.body // "" | [match("<!-- repo-warden:fp=([0-9a-f]{16}) src=([A-Za-z0-9._:/-]+) -->"; "g")] | last) as $m
      | select($m != null)
      | [$i.number, $m.captures[0].string, $m.captures[1].string, ([$i.labels[]?.name] | join(","))] | @tsv' 2>/dev/null)
  else
    err "no se pudo listar los issues abiertos"
  fi
fi

# --- procesar informes ------------------------------------------------------------------------------------
process_finding() { # $1 = JSON del hallazgo
  local f="$1" title body sev rank slalabel src keyraw fp labels
  title="$(jq -r '.title' <<<"$f")"
  sev="$(jq -r '.sev' <<<"$f")"
  rank="$(jq -r '.rank' <<<"$f")"
  slalabel="$(jq -r '.slalabel' <<<"$f")"
  src="$(jq -r '.src' <<<"$f")"
  keyraw="$(jq -r '.keyraw' <<<"$f")"
  body="$(jq -r '.body' <<<"$f")"
  fp="$(printf '%s' "$keyraw" | sha256sum | cut -c1-16)"
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
  printf '%s\n<!-- repo-warden:fp=%s src=%s -->\n' "$body" "$fp" "$src" >"$BODY_FILE"
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
echo "Resumen: $TOTAL hallazgos, $CREATED creados, $EXISTING existentes, $UPDATED con plazo actualizado, $RESOLVED con aviso de resuelto, $SKIPPED_LIMIT sin crear por el límite."
[ "$ERRORS" -eq 0 ] || exit 1
exit 0
