import { useEffect, useState } from "react";
import { History, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { deleteDeliveryConversation, renameDeliveryConversation } from "@/lib/api";
import { useDeliveryConversationsQuery } from "@/lib/queries/delivery";
import { queryKeys } from "@/lib/queries/keys";
import type { DeliveryChatConversationSummary } from "@/types/delivery-chat";

type DeliveryHistoryPopoverProps = {
  asking: boolean;
  projectId?: string | null;
  activeConversationId?: string | null;
  onSelectConversation: (conversationId: string) => void | Promise<void>;
  onNewConversation: () => void;
};

export function DeliveryHistoryPopover({
  asking,
  projectId,
  activeConversationId,
  onSelectConversation,
  onNewConversation,
}: DeliveryHistoryPopoverProps) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const historyQuery = useDeliveryConversationsQuery(projectId ?? null, open);
  const conversations = historyQuery.data ?? [];
  const loading = open && historyQuery.isFetching && conversations.length === 0;

  const [renameTarget, setRenameTarget] = useState<DeliveryChatConversationSummary | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<DeliveryChatConversationSummary | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState(false);

  useEffect(() => {
    if (open) {
      void historyQuery.refetch();
    }
  }, [historyQuery.refetch, open]);

  const invalidateHistory = async () => {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.deliveryConversations(projectId ?? null),
    });
  };

  const handleRename = async () => {
    if (!renameTarget) return;
    const title = renameValue.trim();
    if (!title) {
      setActionError("Title cannot be empty.");
      return;
    }
    setActionPending(true);
    setActionError(null);
    try {
      await renameDeliveryConversation(renameTarget.id, title);
      setRenameTarget(null);
      await invalidateHistory();
    } catch {
      setActionError("Could not rename this conversation. Please try again.");
    } finally {
      setActionPending(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setActionPending(true);
    setActionError(null);
    try {
      await deleteDeliveryConversation(deleteTarget.id);
      if (activeConversationId === deleteTarget.id) {
        onNewConversation();
      }
      setDeleteTarget(null);
      await invalidateHistory();
    } catch {
      setActionError("Could not delete this conversation. Please try again.");
    } finally {
      setActionPending(false);
    }
  };

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={asking}
            className="h-8 gap-1.5 px-2 text-xs text-muted-foreground"
          >
            <History className="h-3.5 w-3.5" />
            History
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-80 p-2">
          <div className="mb-2 px-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Saved conversations
          </div>
          {loading ? (
            <p className="px-1 py-2 text-xs text-muted-foreground">Loading conversations...</p>
          ) : historyQuery.isError ? (
            <p className="px-1 py-2 text-xs text-destructive">Could not load saved conversations.</p>
          ) : conversations.length === 0 ? (
            <p className="px-1 py-2 text-xs text-muted-foreground">No saved conversations yet.</p>
          ) : (
            <div className="max-h-72 space-y-1 overflow-y-auto">
              {conversations.map((conversation) => {
                const isActive = activeConversationId === conversation.id;
                return (
                  <div
                    key={conversation.id}
                    className={`group relative rounded-md transition-colors hover:bg-secondary ${
                      isActive ? "bg-secondary/80 ring-1 ring-border" : ""
                    }`}
                  >
                    <button
                      type="button"
                      disabled={asking}
                      onClick={() => {
                        void onSelectConversation(conversation.id);
                        setOpen(false);
                      }}
                      className="w-full rounded-md px-2 py-1.5 pr-8 text-left text-xs transition-colors disabled:opacity-50"
                    >
                      <span className="line-clamp-2 font-medium text-foreground">{conversation.title}</span>
                      <span className="mt-0.5 block text-[10px] text-muted-foreground">
                        {conversation.turn_count} question{conversation.turn_count === 1 ? "" : "s"} ·{" "}
                        {new Date(conversation.updated_at).toLocaleString()}
                      </span>
                    </button>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="absolute right-0.5 top-1/2 h-7 w-7 -translate-y-1/2 opacity-0 group-hover:opacity-100"
                          disabled={asking || actionPending}
                          onClick={(event) => event.stopPropagation()}
                        >
                          <MoreHorizontal className="h-3.5 w-3.5" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-36">
                        <DropdownMenuItem
                          onClick={() => {
                            setRenameTarget(conversation);
                            setRenameValue(conversation.title);
                            setActionError(null);
                          }}
                        >
                          <Pencil className="mr-2 h-3.5 w-3.5" />
                          Rename
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          className="text-destructive focus:text-destructive"
                          onClick={() => {
                            setDeleteTarget(conversation);
                            setActionError(null);
                          }}
                        >
                          <Trash2 className="mr-2 h-3.5 w-3.5" />
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                );
              })}
            </div>
          )}
        </PopoverContent>
      </Popover>

      <AlertDialog open={renameTarget !== null} onOpenChange={(next) => !next && setRenameTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Rename conversation</AlertDialogTitle>
            <AlertDialogDescription>
              Choose a title that helps you find this thread later.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <Input
            value={renameValue}
            maxLength={120}
            onChange={(event) => setRenameValue(event.target.value)}
            placeholder="Conversation title"
          />
          {actionError ? <p className="text-xs text-destructive">{actionError}</p> : null}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={actionPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction disabled={actionPending} onClick={() => void handleRename()}>
              Save
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={deleteTarget !== null} onOpenChange={(next) => !next && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete conversation?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently removes &ldquo;{deleteTarget?.title}&rdquo; and all of its messages.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {actionError ? <p className="text-xs text-destructive">{actionError}</p> : null}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={actionPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={actionPending}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => void handleDelete()}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
