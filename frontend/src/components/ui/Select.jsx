import React from 'react';

export function Select({ label, error, id, className = '', children, ...props }) {
  return (
    <div className="form-group">
      {label && <label className="form-label" htmlFor={id}>{label}</label>}
      <select 
        id={id}
        className={`form-control ${error ? 'is-invalid' : ''} ${className}`} 
        {...props} 
      >
        {children}
      </select>
      {error && <span className="invalid-feedback">{error}</span>}
    </div>
  );
}
