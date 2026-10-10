import React from 'react';

export function Table({ className = '', children, ...props }) {
  return (
    <div className={`table-wrapper ${className}`}>
      <table className="ui-table" {...props}>
        {children}
      </table>
    </div>
  );
}
