import { StudentOnboarding } from "@/components/student-onboarding";
export default function OnboardingPage() {
  return <main className="mx-auto max-w-3xl space-y-6 px-6 py-10"><nav className="flex gap-5 text-teal-700"><a href="/">PamatiAI</a><a href="/student/privacy">Your privacy and records</a><a href="/auth/profile">Account</a></nav><h1 className="text-3xl font-semibold">Understand PamatiAI and choose what to share</h1><StudentOnboarding /></main>;
}
