import { MakeView } from "@/components/MakeView";
import { ModeTabs } from "@/components/ModeTabs";

export default function MakePage() {
  return (
    <div className="flex flex-col h-dvh">
      <ModeTabs active="make" />
      <MakeView />
    </div>
  );
}
