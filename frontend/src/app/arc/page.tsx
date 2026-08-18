import type { Metadata } from "next";
import { ArcView } from "@/components/ArcView";
import { ModeTabs } from "@/components/ModeTabs";
import { MobileNav } from "@/components/MobileNav";

export const metadata: Metadata = {
  title: "Arc",
  description: "Your most-summoned template, your longest streak, and an aura score that goes up whether you like it or not.",
};

export default function ArcPage() {
  return (
    <div className="flex flex-col h-dvh">
      <ModeTabs active="arc" />
      <ArcView />
      <MobileNav active="arc" />
    </div>
  );
}
