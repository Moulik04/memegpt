import type { Metadata } from "next";
import { MakeView } from "@/components/MakeView";
import { ModeTabs } from "@/components/ModeTabs";
import { MobileNav } from "@/components/MobileNav";

export const metadata: Metadata = {
  title: "Make",
  description: "Pick a template yourself and write your own captions, box by box.",
};

export default function MakePage() {
  return (
    <div className="flex flex-col h-dvh">
      <ModeTabs active="make" />
      <MakeView />
      <MobileNav active="make" />
    </div>
  );
}
