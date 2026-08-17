import { MakeView } from "@/components/MakeView";
import { ModeTabs } from "@/components/ModeTabs";
import { MobileNav } from "@/components/MobileNav";

export default function MakePage() {
  return (
    <div className="flex flex-col h-dvh">
      <ModeTabs active="make" />
      <MakeView />
      <MobileNav active="make" />
    </div>
  );
}
