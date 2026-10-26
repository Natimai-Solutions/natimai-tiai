import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('pages/LoginPage.vue'),
    meta: { title: 'Connexion' },
  },
  // Parcours « mot de passe oublié » : pages publiques, atteintes sans session
  // (depuis la page de connexion, ou depuis le lien reçu par e-mail).
  {
    path: '/forgot-password',
    name: 'forgot-password',
    component: () => import('pages/ForgotPasswordPage.vue'),
    meta: { title: 'Mot de passe oublié' },
  },
  {
    path: '/reset-password',
    name: 'reset-password',
    component: () => import('pages/ResetPasswordPage.vue'),
    meta: { title: 'Nouveau mot de passe' },
  },
  {
    path: '/',
    component: () => import('layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'dashboard',
        component: () => import('pages/DashboardPage.vue'),
        meta: { title: 'Tableau de bord' },
      },
      {
        path: 'machines',
        name: 'machines',
        component: () => import('pages/MachinesPage.vue'),
        meta: { title: 'Postes' },
      },
      {
        path: 'software',
        name: 'software',
        component: () => import('pages/SoftwarePage.vue'),
        meta: { title: 'Logiciels' },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('pages/SettingsPage.vue'),
        meta: { title: 'Paramètres', requiresPermission: 'settings:read' },
      },
      {
        path: 'tasks',
        name: 'tasks',
        component: () => import('pages/TasksPage.vue'),
        meta: { title: 'Mes tâches', requiresPermission: 'check:read' },
      },
      {
        path: 'rooms',
        name: 'rooms',
        component: () => import('pages/RoomsPage.vue'),
        meta: { title: 'Salles', requiresPermission: 'room:read' },
      },
      {
        path: 'rooms/:id',
        name: 'room-detail',
        component: () => import('pages/RoomDetailPage.vue'),
        props: true,
        meta: { title: 'Salle', requiresPermission: 'room:read' },
      },
      {
        path: 'machines/:id',
        name: 'machine-detail',
        component: () => import('pages/MachineDetailPage.vue'),
        props: true,
        meta: { title: 'Poste' },
      },
      {
        path: 'users',
        name: 'users',
        component: () => import('pages/UsersPage.vue'),
        meta: { title: 'Utilisateurs', requiresPermission: 'user:read' },
      },
      {
        path: 'groups',
        name: 'groups',
        component: () => import('pages/GroupsPage.vue'),
        meta: { title: 'Groupes', requiresPermission: 'user:read' },
      },
      {
        path: 'audit',
        name: 'audit',
        component: () => import('pages/AuditPage.vue'),
        meta: { title: "Journal d'audit", requiresPermission: 'audit:read' },
      },
      {
        path: 'account',
        name: 'account',
        component: () => import('pages/AccountPage.vue'),
        meta: { title: 'Mon compte' },
      },
    ],
  },
  {
    path: '/:catchAll(.*)*',
    meta: { title: 'Page introuvable' },
    component: () => import('pages/ErrorNotFound.vue'),
  },
];

export default routes;
