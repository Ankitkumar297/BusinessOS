import { useEffect, useRef, type PropsWithChildren } from "react";

export function Dialog({ title, children, close }: PropsWithChildren<{ title: string; close: () => void }>): JSX.Element {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const dialog = ref.current; dialog?.showModal(); return () => dialog?.close(); }, []);
  return <dialog ref={ref} onCancel={event => { event.preventDefault(); close(); }} className="rounded-2xl bg-transparent p-0 backdrop:bg-gray-950/40">
    <section role="dialog" aria-modal="true" aria-label={title} className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white p-6 shadow-xl">
      <div className="mb-5 flex items-center justify-between"><h2 className="text-xl font-semibold">{title}</h2><button aria-label="Close dialog" onClick={close} className="rounded p-2 text-gray-500">✕</button></div>{children}
    </section></dialog>;
}

export function Feedback({ error, success }: { error?: string; success?: string }): JSX.Element | null {
  if (error) return <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>;
  if (success) return <p role="status" className="rounded-lg bg-green-50 p-3 text-sm text-green-700">{success}</p>;
  return null;
}
