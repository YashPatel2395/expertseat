export default function Home() {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center p-8">
      <h1 className="text-3xl font-bold">ExpertSeat</h1>
      <p className="mt-2 text-lg text-gray-600">Add the missing expert to any interview panel.</p>
      <p className="mt-4 max-w-xl text-center text-gray-500">
        ExpertSeat is a recruiter-controlled AI interview panelist platform. AI Role Agents
        participate as disclosed panelists, ask evidence-backed questions, and produce reports that
        human reviewers assess.
      </p>
      <div className="mt-6 px-4 py-2 bg-yellow-100 border border-yellow-300 rounded text-yellow-800 text-sm">
        Foundation development — no product features are available yet.
      </div>
    </main>
  );
}
