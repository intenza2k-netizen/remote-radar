import Link from "next/link";
import { Container, PageHeader } from "@/components/ui";

export default function NotFound() {
  return (
    <Container className="pb-16">
      <PageHeader
        eyebrow="404"
        title="That page is not in the snapshot"
        lede={
          <>
            The skill or page you asked for does not exist (yet). Try the{" "}
            <Link href="/skills" className="link">
              skills table
            </Link>{" "}
            or go back to the{" "}
            <Link href="/" className="link">
              overview
            </Link>
            .
          </>
        }
      />
    </Container>
  );
}
