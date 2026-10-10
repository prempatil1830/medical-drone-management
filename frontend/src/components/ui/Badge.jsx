import React from 'react';

export function Badge({ variant = 'default', className = '', children, ...props }) {
  return (
    <span className={`badge badge-${variant} ${className}`} {...props}>
      {children}
    </span>
  );
}
