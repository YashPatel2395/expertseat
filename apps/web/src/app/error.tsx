"use client";
import { useEffect } from "react";
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <main className="min-h-screen flex flex-col items-center justify-center p-8">
      <h2 className="text-xl font-bold">Something went wrong.</h2>
      <button onClick={reset} className="mt-4 px-4 py-2 bg-gray-100 rounded">
        Try again
      </button>
    </main>
  );
}
