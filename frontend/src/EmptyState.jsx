export default function AdminEmptyState({ icon, title, description, ctaLabel, onCta }) {
  return (
    <div className="ap-empty-state">
      {icon && <div className="ap-empty-state__icon" aria-hidden="true"><i className={`fas fa-${icon}`} /></div>}
      {title && <h3 className="ap-empty-state__title">{title}</h3>}
      {description && <p className="ap-empty-state__desc">{description}</p>}
      {ctaLabel && onCta && (
        <button type="button" className="ap-btn primary" onClick={onCta} style={{ marginTop: 12 }}>
          {ctaLabel}
        </button>
      )}
    </div>
  );
}
