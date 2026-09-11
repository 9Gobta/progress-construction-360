import { redirect } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { FieldNotesWorkspace } from "@/components/field-notes-workspace";
import { getCurrentUser, getFieldNotes, getProject, getProjectMembers } from "@/lib/server-api";

export default async function FieldNotesPage({ params }: { params: Promise<{ projectId: string }> }) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const { projectId } = await params;
  const [project, notes, members] = await Promise.all([
    getProject(projectId), getFieldNotes(projectId), getProjectMembers(projectId),
  ]);
  const canEdit = project.role === "admin" || project.role === "sub_admin" || project.role === "reviewer";
  return <div className="app-frame">
    <AppHeader user={user} viewerTitle={`${project.name} · ประเด็นหน้างาน`} />
    <main className="standalone-main"><FieldNotesWorkspace canEdit={canEdit} members={members} notes={notes} projectId={projectId} /></main>
  </div>;
}
