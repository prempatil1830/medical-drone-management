import React from 'react';
import { Inbox } from 'lucide-react';

export function EmptyState({ icon: Icon = Inbox, title, description, className = '', ...props }) {
  return (
    <div className={`empty-state ${className}`} {...props}>
      <Icon className="empty-icon" size={48} strokeWidth={1.5} />
      <h3 className="empty-title">{title}</h3>
      {description && <p className="empty-description">{description}</p>}
    </div>
  );
}
