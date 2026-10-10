import React from 'react';

export function Button({ variant = 'primary', className = '', children, ...props }) {
  const variantClass = variant === 'primary' ? 'btn-primary' : 
                       variant === 'secondary' ? 'btn-secondary' : 
                       variant === 'destructive' ? 'btn-destructive' : 'btn-primary';
  return (
    <button className={`btn ${variantClass} ${className}`} {...props}>
      {children}
    </button>
  );
}
