import { ArcView } from "@/components/ArcView";
import { ModeTabs } from "@/components/ModeTabs";
import { MobileNav } from "@/components/MobileNav";

export default function ArcPage() {
  return (
    <div className="flex flex-col h-dvh">
      <ModeTabs active="arc" />
      <ArcView />
      <MobileNav active="arc" />
    </div>
  );
}
