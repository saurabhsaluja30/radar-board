import React from "react";
import { Loader2, SearchX } from "lucide-react";
import { toast } from "sonner";

export const notify = (msg, type = "info") =>
  type === "success" ? toast.success(msg) : type === "error" ? toast.error(msg) : toast(msg);

export const errMsg = (e) => e?.message || "Something went wrong. Please try again.";

const SIZE = { sm: "btn-sm", md: "btn-md", lg: "btn-lg" };
const VARIANT = { primary: "btn-primary", secondary: "btn-secondary", outline: "btn-outline", ghost: "btn-ghost", danger: "btn-danger" };

export function Button({ title, children, onClick, variant = "primary", size = "md", loading, disabled, full, icon, className = "", type = "button", ...rest }) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || loading}
      className={`btn ${SIZE[size]} ${VARIANT[variant]} ${full ? "w-full" : ""} ${className}`}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {title || children}
    </button>
  );
}

export const Card = ({ children, className = "", ...rest }) => (
  <div className={`card ${className}`} {...rest}>{children}</div>
);

const BADGE = {
  success: "bg-emerald-100 text-emerald-700",
  warning: "bg-amber-100 text-amber-700",
  error: "bg-red-100 text-red-700",
  info: "bg-brand-soft text-gray-600",
  brand: "bg-brand-soft text-brand",
};
export const Badge = ({ label, color = "info", ...rest }) => (
  <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide ${BADGE[color]}`} {...rest}>
    {label}
  </span>
);

export function Input({ label, hint, multiline, rows = 4, className = "", ...props }) {
  const Tag = multiline ? "textarea" : "input";
  return (
    <label className={`block ${className}`}>
      {label ? <span className="label">{label}</span> : null}
      <Tag className={`field ${multiline ? "resize-y" : ""}`} rows={multiline ? rows : undefined} {...props} />
      {hint ? <span className="mt-1 block text-xs text-gray-500">{hint}</span> : null}
    </label>
  );
}

export const Chip = ({ label, selected, onClick, ...rest }) => (
  <button type="button" onClick={onClick} className={`chip ${selected ? "chip-on" : "chip-off"}`} {...rest}>
    {label}
  </button>
);

export function ChipRow({ label, children }) {
  return (
    <div>
      {label ? <span className="label">{label}</span> : null}
      <div className="flex flex-wrap gap-2">{children}</div>
    </div>
  );
}

export const SectionTitle = ({ title, action, onAction }) => (
  <div className="mb-4 flex items-center justify-between">
    <h2 className="h-sec">{title}</h2>
    {action ? (
      <button onClick={onAction} className="text-sm font-bold text-brand hover:underline">{action}</button>
    ) : null}
  </div>
);

export const EmptyState = ({ title, subtitle, ...rest }) => (
  <div className="flex flex-col items-center py-14 text-center" {...rest}>
    <SearchX className="mb-3 h-10 w-10 text-brand/60" />
    <p className="text-base font-bold text-gray-800">{title}</p>
    {subtitle ? <p className="muted mt-1">{subtitle}</p> : null}
  </div>
);

export const Spinner = () => (
  <div className="flex justify-center py-16"><Loader2 className="h-7 w-7 animate-spin text-brand" /></div>
);

export function PageHeader({ title, subtitle, right }) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="h-page">{title}</h1>
        {subtitle ? <p className="mt-2 max-w-2xl text-gray-500">{subtitle}</p> : null}
      </div>
      {right}
    </div>
  );
}

export function Switch({ checked, onChange, ...rest }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative h-6 w-11 rounded-full transition-colors ${checked ? "bg-brand" : "bg-gray-300"}`}
      {...rest}
    >
      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${checked ? "translate-x-5" : "translate-x-0.5"}`} />
    </button>
  );
}

export function Modal({ open, onClose, children, wide }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6 backdrop-blur-sm" onClick={onClose}>
      <div className={`max-h-[90vh] w-full overflow-auto rounded-2xl bg-white p-6 shadow-2xl ${wide ? "max-w-3xl" : "max-w-md"}`} onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}
