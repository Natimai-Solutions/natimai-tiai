import type { RouteRecordRaw } from 'vue-router';

// `meta.title` is a key of the catalogues (`layout.pages.*`): the router
// translates it into the tab's title, again on each change of language.

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('pages/LoginPage.vue'),
    meta: { title: 'layout.pages.login' },
  },
  // Parcours « mot de passe oublié » : pages publiques, atteintes sans session
  // (depuis la page de connexion, ou depuis le lien reçu par e-mail).
  {
    path: '/forgot-password',
    name: 'forgot-password',
    component: () => import('pages/ForgotPasswordPage.vue'),
    meta: { title: 'layout.pages.forgotPassword' },
  },
  {
    path: '/reset-password',
    name: 'reset-password',
    component: () => import('pages/ResetPasswordPage.vue'),
    meta: { title: 'layout.pages.resetPassword' },
  },
  // A sheet of labels to print: outside the console's frame. Not under
  // /assets: nginx serves the build's hashed files there, with no way back
  // to the console on a reload (`nginx.conf`).
  {
    path: '/equipment/labels',
    name: 'asset-labels',
    component: () => import('pages/AssetLabelsPage.vue'),
    meta: {
      title: 'layout.pages.assetLabels',
      requiresAuth: true,
      requiresPermission: 'asset:read',
    },
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
        meta: { title: 'layout.pages.dashboard', requiresPermission: 'machine:read' },
      },
      {
        path: 'machines',
        name: 'machines',
        component: () => import('pages/MachinesPage.vue'),
        meta: { title: 'layout.pages.machines', requiresPermission: 'machine:read' },
      },
      {
        path: 'alerts',
        name: 'alerts',
        component: () => import('pages/AlertsPage.vue'),
        meta: { title: 'layout.pages.alerts', requiresPermission: 'machine:read' },
      },
      {
        // « equipment », not « assets »: the build's own directory (above).
        path: 'equipment',
        name: 'assets',
        component: () => import('pages/AssetsPage.vue'),
        meta: { title: 'layout.pages.assets', requiresPermission: 'asset:read' },
      },
      {
        path: 'schedules',
        name: 'schedules',
        component: () => import('pages/SchedulesPage.vue'),
        meta: { title: 'layout.pages.schedules', requiresPermission: 'schedule:read' },
      },
      {
        // Where a printed label's QR code leads: the poste behind it.
        path: 'a/:token',
        name: 'asset-token',
        component: () => import('pages/AssetTokenPage.vue'),
        meta: { title: 'layout.pages.assetToken', requiresPermission: 'machine:read' },
      },
      {
        path: 'software',
        name: 'software',
        component: () => import('pages/SoftwarePage.vue'),
        meta: { title: 'layout.pages.software', requiresPermission: 'machine:read' },
      },
      {
        path: 'packages',
        name: 'packages',
        component: () => import('pages/PackagesPage.vue'),
        meta: { title: 'layout.pages.packages', requiresPermission: 'package:read' },
      },
      {
        path: 'packages/:id',
        name: 'package-detail',
        component: () => import('pages/PackageDetailPage.vue'),
        props: true,
        meta: { title: 'layout.pages.package', requiresPermission: 'package:read' },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('pages/SettingsPage.vue'),
        meta: { title: 'layout.pages.settings', requiresPermission: 'settings:read' },
      },
      {
        path: 'tasks',
        name: 'tasks',
        component: () => import('pages/TasksPage.vue'),
        // Either suffices: an account that only owns maintenances is sent
        // here by its reminders (/tasks), and the page shows what it reads.
        meta: {
          title: 'layout.pages.tasks',
          requiresPermission: ['check:read', 'maintenance:read'],
        },
      },
      {
        path: 'rooms',
        name: 'rooms',
        component: () => import('pages/RoomsPage.vue'),
        meta: { title: 'layout.pages.rooms', requiresPermission: 'room:read' },
      },
      {
        path: 'rooms/:id',
        name: 'room-detail',
        component: () => import('pages/RoomDetailPage.vue'),
        props: true,
        meta: { title: 'layout.pages.room', requiresPermission: 'room:read' },
      },
      {
        path: 'machines/:id',
        name: 'machine-detail',
        component: () => import('pages/MachineDetailPage.vue'),
        props: true,
        meta: { title: 'layout.pages.machine', requiresPermission: 'machine:read' },
      },
      {
        path: 'users',
        name: 'users',
        component: () => import('pages/UsersPage.vue'),
        meta: { title: 'layout.pages.users', requiresPermission: 'user:read' },
      },
      {
        path: 'groups',
        name: 'groups',
        component: () => import('pages/GroupsPage.vue'),
        meta: { title: 'layout.pages.groups', requiresPermission: 'user:read' },
      },
      {
        path: 'audit',
        name: 'audit',
        component: () => import('pages/AuditPage.vue'),
        meta: { title: 'layout.pages.audit', requiresPermission: 'audit:read' },
      },
      {
        path: 'account',
        name: 'account',
        component: () => import('pages/AccountPage.vue'),
        meta: { title: 'layout.pages.account' },
      },
      {
        // Where an account whose groups grant nothing to read lands.
        path: 'no-access',
        name: 'no-access',
        component: () => import('pages/NoAccessPage.vue'),
        meta: { title: 'layout.pages.noAccess' },
      },
    ],
  },
  {
    path: '/:catchAll(.*)*',
    meta: { title: 'layout.pages.notFound' },
    component: () => import('pages/ErrorNotFound.vue'),
  },
];

export default routes;
