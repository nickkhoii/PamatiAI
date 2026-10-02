import { ServiceStatus } from "@/components/service-status";

const portals = [
  ["Student space", "Conversations, independent consent choices, personal history and data controls."],
  ["Reviewer workspace", "Assigned student trends and support signals, with documented human review."],
  ["Administration", "Account and configuration management with restricted access to student content."]
];

export default function Home() {
  return <>
    <header className="border-b border-slate-200 bg-white"><div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-6 py-5"><span className="text-2xl font-bold tracking-tight">Pamati<span className="text-teal-700">AI</span></span><span className="rounded-full bg-teal-50 px-3 py-1 text-sm text-teal-900">Research prototype · Foundation</span></div></header>
    <main id="main" className="mx-auto max-w-6xl space-y-8 px-6 py-12">
      <section className="max-w-3xl"><p className="text-sm font-semibold uppercase tracking-widest text-teal-800">Student autonomy. Human oversight.</p><h1 className="mt-4 text-4xl font-semibold leading-tight sm:text-5xl">A thoughtful foundation for student support.</h1><p className="mt-5 text-lg leading-relaxed text-slate-600">A Multimodal Conversational AI Framework for Student Mental Health and Sentiment Tracking, designed for higher-education research.</p><p className="mt-4 leading-relaxed">PamatiAI is being developed for consented sentiment and affect analysis over time. It does not diagnose mental-health conditions, prescribe treatment, or replace professional care or emergency services.</p></section>
      <ServiceStatus />
      <section aria-labelledby="portals-title"><h2 id="portals-title" className="mb-4 text-xl font-semibold">Planned workspaces</h2><div className="grid gap-4 md:grid-cols-3">{portals.map(([title, description]) => <article key={title} className="rounded-2xl border border-slate-200 bg-white p-6"><span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Not yet implemented</span><h3 className="mt-3 text-xl font-semibold">{title}</h3><p className="mt-3 leading-relaxed text-slate-600">{description}</p></article>)}</div></section>
      <aside className="rounded-2xl bg-teal-900 p-6 text-white"><h2 className="text-lg font-semibold">Participation stays your choice</h2><p className="mt-2 leading-relaxed text-teal-50">Text, speech and optional visual participation will have separate consent controls. This foundation does not collect messages, media or student records. AI-generated support signals will require authorized human review.</p></aside>
    </main><footer className="mx-auto max-w-6xl px-6 pb-8 text-sm text-slate-600">PamatiAI · Consent, privacy, accessibility and reproducible research.</footer>
  </>;
}
