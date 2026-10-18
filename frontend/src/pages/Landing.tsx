import { Coverage, Features, FinalCta, Footer, ReportMarquee, Results } from "./landing/Sections";
import { Hero } from "./landing/Hero";
import { HowItWorks } from "./landing/HowItWorks";
import { Navbar } from "./landing/Navbar";

export default function Landing() {
  return (
    <div className="min-h-full bg-bg">
      <Navbar />
      <main>
        <Hero />
        <ReportMarquee />
        <HowItWorks />
        <Features />
        <Results />
        <Coverage />
        <FinalCta />
      </main>
      <Footer />
    </div>
  );
}
