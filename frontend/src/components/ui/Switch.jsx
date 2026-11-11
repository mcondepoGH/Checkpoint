import React from 'react';

// Interruptor accesible: checkbox real con role=switch; el control visual es decorativo. label: texto junto al interruptor.
export default function Switch({ label, ...rest }) {
  return (
    <label className="switch">
      <input type="checkbox" role="switch" {...rest} />
      <span className="track" aria-hidden="true">
        <i />
      </span>
      <span>{label}</span>
    </label>
  );
}
