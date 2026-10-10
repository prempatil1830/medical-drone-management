import React from 'react';

export function Input({ label, error, id, className = '', ...props }) {
  return (
    <div className="form-group">
      {label && <label className="form-label" htmlFor={id}>{label}</label>}
      <input 
        id={id}
        className={`form-control ${error ? 'is-invalid' : ''} ${className}`} 
        {...props} 
      />
      {error && <span className="invalid-feedback">{error}</span>}
    </div>
  );
}
