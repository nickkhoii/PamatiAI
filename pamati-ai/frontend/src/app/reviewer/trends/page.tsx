import { LongitudinalTrends } from "../../../components/longitudinal-trends";

export default function ReviewerTrends() {
  return <main id="main" className="mx-auto max-w-5xl space-y-6 p-6"><h1 className="text-2xl font-semibold">Assigned student trends</h1><p>Access requires a current assignment and the student's reviewer-access and longitudinal-tracking permissions.</p><LongitudinalTrends reviewer /></main>;
}
