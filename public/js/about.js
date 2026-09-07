const aboutMembers = document.querySelector('#aboutMembers');

async function loadAboutMembers() {
  if (!aboutMembers) return;
  const projects = await request('/projects?search=NetHub');
  const project = (projects.data || []).find(
    (item) => String(item.name || '').trim().toLowerCase() === 'nethub',
  );
  if (!project) throw new Error('NetHub project not found');
  const result = await request(`/projects/${encodeURIComponent(project.id)}`);
  if (!result.data) throw new Error('NetHub project unavailable');
  aboutMembers.innerHTML = projectMembers.render(result.data);
  projectMembers.bind(aboutMembers);
}

loadAboutMembers().catch(() => {
  if (aboutMembers) {
    aboutMembers.innerHTML = '<div class="empty">暂时无法加载成员信息，请稍后刷新，或前往 <a href="/projects.html?search=NetHub">CAS 项目库</a> 查看。</div>';
  }
});
