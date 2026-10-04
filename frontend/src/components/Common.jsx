import React, { useState } from "react";
import { Check, Copy, FileText } from "lucide-react";
export const readable = (value) => (value || "WAITING").replaceAll("_", " ");
export const timeOnly = (value) => value?.split("T")[1] || "—";
export function Status({ state }) {
  return (
    <span className={`status status-${state || "WAITING"}`}>
      <i />
      {readable(state)}
    </span>
  );
}
export function CopyButton({ text, label = "Copy" }) {
  const [result, setResult] = useState("");
  return (
    <button
      className="icon-button"
      title={label}
      aria-label={label}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setResult("Copied");
        } catch {
          setResult("Copy unavailable");
        }
      }}
    >
      {result === "Copied" ? <Check size={14} /> : <Copy size={14} />}
      {result && <span role="status">{result}</span>}
    </button>
  );
}
export function Evidence({
  raw,
  label = "View raw evidence",
  sourceLabel = "ORIGINAL CORE LOG",
  fallback = "Timer-generated timeout. No matching log line.",
}) {
  return (
    <details className="evidence">
      <summary>
        <FileText size={13} />
        {label}
      </summary>
      <div className="evidence-body">
        <div className="console-label">
          <span>{sourceLabel}</span>
          {raw && <CopyButton text={raw} label="Copy raw evidence" />}
        </div>
        <pre>{raw ?? fallback}</pre>
      </div>
    </details>
  );
}
export function Fields({ fields, className = "" }) {
  return (
    <dl className={`fields ${className}`}>
      {fields.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}
export function Empty({ icon: Icon = FileText, title, text }) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon size={25} />
      </span>
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  );
}
