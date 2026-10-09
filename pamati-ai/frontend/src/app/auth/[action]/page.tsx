import { notFound } from "next/navigation";
import { AuthForm } from "@/components/auth-form";
import { PamatiMark, PamatiMascot } from "@/components/pamati-mascot";

const titles: Record<string, string> = { login: "Sign in", register: "Join PamatiAI", invite: "Accept your invitation",
  activate: "Activate your account", reset: "Reset your password", "forgot-password": "Recover your account",
  profile: "Your profile", "change-password": "Change your password" };

export default async function AuthPage({ params }: { params: Promise<{ action: string }> }) {
  const { action } = await params;
  if (!titles[action]) notFound();
  if (action === "login") return <main id="main" className="auth-screen"><section className="auth-panel" aria-labelledby="login-title"><div className="auth-welcome"><a href="/" className="brand"><PamatiMark />Pamati<span>AI</span></a><div className="auth-introduction"><p className="eyebrow">A moment for yourself</p><h2>A space to pause.<br />A place to reflect.</h2><PamatiMascot /><p>Talk, reflect and explore your observations at your own pace.</p></div><p className="auth-safeguard">Your choices matter. AI observations are research signals, and human support remains essential.</p></div><div className="auth-signin"><p className="eyebrow">Welcome back</p><h1 id="login-title">Sign in</h1><p className="auth-description">Continue to your PamatiAI workspace.</p><AuthForm action={action} /><p className="auth-footnote">PamatiAI complements student-support services. It is not a diagnostic system or an emergency service.</p></div></section></main>;
  if (action === "profile") return <main id="main" className="standalone-workspace profile-workspace mx-auto max-w-3xl px-6 py-10"><header className="profile-heading"><a className="brand" href="/"><PamatiMark />Pamati<span>AI</span></a><PamatiMascot compact /></header><p className="eyebrow">Your personal space</p><h1 className="my-3 text-3xl font-semibold">Your profile</h1><p className="profile-description">Manage your account, save your display name, or continue to your workspace.</p><AuthForm action={action} /></main>;
  return <main id="main" className="standalone-workspace mx-auto max-w-lg px-6 py-12"><a href="/" className="text-teal-700">PamatiAI</a>
    <h1 className="my-6 text-3xl font-semibold">{titles[action]}</h1><AuthForm action={action} /></main>;
}
