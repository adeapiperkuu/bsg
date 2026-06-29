import { PageLoadingScreen } from "@/components/bsg/PageLoadingScreen";

type Props = {
  className?: string;
};

export function KnowledgeLoadingScreen(props: Props) {
  return <PageLoadingScreen {...props} />;
}
