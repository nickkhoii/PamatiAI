import { notFound } from "next/navigation";
import { AuthForm } from "@/components/auth-form";

const titles: Record<string, string> = { login: "Sign in", register: "Join PamatiAI", invite: "Accept your invitation",
  activate: "Activate your account", reset: "Reset your password", "forgot-password": "Recover your account",
  profile: "Your profile", "change-password": "Change your password" };

export default async function AuthPage({ params }: { params: Promise<{ action: string }> }) {
  const { action } = await params;
  if (!titles[action]) notFound();
  return <main className="mx-auto max-w-lg px-6 py-12"><a href="/" className="text-teal-700">PamatiAI</a>
    <h1 className="my-6 text-3xl font-semibold">{titles[action]}</h1><AuthForm action={action} /></main>;
}
