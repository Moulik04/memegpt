import { ArcView } from "@/components/ArcView";
import { ModeTabs } from "@/components/ModeTabs";

export default function ArcPage() {
  return (
    <div className="flex flex-col h-dvh">
      <ModeTabs active="arc" />
      <ArcView />
    </div>
  );
}
