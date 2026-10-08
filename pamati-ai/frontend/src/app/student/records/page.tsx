import { StudentRecords } from "@/components/student-records";
import { LongitudinalTrends } from "@/components/longitudinal-trends";
export default function RecordsPage() { return <main id="main" className="mx-auto max-w-5xl space-y-6 px-6 py-10"><nav className="flex gap-5"><a href="/student/privacy">Privacy controls</a><a href="/student/onboarding">Consent choices</a></nav><h1 className="text-3xl font-semibold">Your available personal records</h1><LongitudinalTrends /><StudentRecords /></main>; }
