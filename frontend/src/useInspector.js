import { useEffect, useState } from "react";
const endpoints = [
  "health",
  "registrations",
  "ues",
  "registration",
  "uncorrelated",
];
export function useInspector() {
  const [snapshot, setSnapshot] = useState(null);
  const [error, setError] = useState("");
  const [updatedAt, setUpdatedAt] = useState(null);
  useEffect(() => {
    let stopped = false,
      timer;
    const controller = new AbortController();
    async function poll() {
      try {
        const results = await Promise.all(
          endpoints.map(async (endpoint) => {
            const response = await fetch(`/api/${endpoint}`, {
              signal: controller.signal,
            });
            if (!response.ok)
              throw new Error(`API returned HTTP ${response.status}`);
            return response.json();
          }),
        );
        if (!stopped) {
          const [health, attempts, ues, waiting, uncorrelated] = results;
          setSnapshot({ health, attempts, ues, waiting, uncorrelated });
          setError("");
          setUpdatedAt(new Date());
        }
      } catch (e) {
        if (!stopped) setError(e.message);
      }
      if (!stopped) timer = setTimeout(poll, 1000);
    }
    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, []);
  return { snapshot, error, updatedAt };
}
