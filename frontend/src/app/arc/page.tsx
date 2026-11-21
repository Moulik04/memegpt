import type { Metadata } from "next";
import { BackendWake } from "@/components/BackendWake";
import { ArcView } from "@/components/ArcView";
import { Masthead } from "@/components/Masthead";
import { MobileNav } from "@/components/MobileNav";

export const metadata: Metadata = {
  title: "Arc",
  description: "Your most-summoned template, your longest streak, and an aura score that goes up whether you like it or not.",
};

export default function ArcPage() {
  return (
    <div className="flex flex-col h-dvh">
      <BackendWake />
      <Masthead variant="app" active="arc" />
      <ArcView />
      <MobileNav active="arc" />
    </div>
  );
}
