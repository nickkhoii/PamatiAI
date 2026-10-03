import { StudentPrivacy } from "@/components/student-privacy";
export default function PrivacyPage() {
  return <main className="mx-auto max-w-3xl space-y-6 px-6 py-10"><nav className="flex gap-5 text-teal-700"><a href="/">PamatiAI</a><a href="/student/onboarding">Consent choices</a><a href="/auth/profile">Account</a></nav><h1 className="text-3xl font-semibold">Your privacy and available records</h1><StudentPrivacy /></main>;
}
