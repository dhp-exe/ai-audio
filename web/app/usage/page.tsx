import { UsageView } from "@/components/UsageView";

export default function UsagePage() {
  return (
    <main className="mx-auto max-w-[1200px] p-5">
      <h1 className="text-[17px] font-semibold">Usage and limits</h1>
      <p className="mt-1 mb-4 text-[13px] text-muted">What each model has consumed in its current period, which ones are refused right now, and when they come back.</p>
      <UsageView />
    </main>
  );
}
