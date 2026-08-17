import { LoreView } from "@/components/LoreView";
import { ModeTabs } from "@/components/ModeTabs";
import { MobileNav } from "@/components/MobileNav";

export default function LorePage() {
  return (
    <div className="flex flex-col h-full">
      <ModeTabs active="lore" />
      <LoreView />
      <MobileNav active="lore" />
    </div>
  );
}
