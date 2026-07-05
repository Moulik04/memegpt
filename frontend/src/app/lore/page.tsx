import { LoreView } from "@/components/LoreView";
import { ModeTabs } from "@/components/ModeTabs";

export default function LorePage() {
  return (
    <div className="flex flex-col h-dvh">
      <ModeTabs active="lore" />
      <LoreView />
    </div>
  );
}
