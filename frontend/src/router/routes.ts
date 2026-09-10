import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('pages/LoginPage.vue'),
  },
  // Parcours « mot de passe oublié » : pages publiques, atteintes sans session
  // (depuis la page de connexion, ou depuis le lien reçu par e-mail).
  {
    path: '/forgot-password',
    name: 'forgot-password',
    component: () => import('pages/ForgotPasswordPage.vue'),
  },
  {
    path: '/reset-password',
    name: 'reset-password',
    component: () => import('pages/ResetPasswordPage.vue'),
  },
  {
    path: '/',
    component: () => import('layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', name: 'dashboard', component: () => import('pages/DashboardPage.vue') },
      { path: 'machines', name: 'machines', component: () => import('pages/MachinesPage.vue') },
      { path: 'software', name: 'software', component: () => import('pages/SoftwarePage.vue') },
      {
        path: 'rooms',
        name: 'rooms',
        component: () => import('pages/RoomsPage.vue'),
        meta: { requiresPermission: 'room:read' },
      },
      {
        path: 'rooms/:id',
        name: 'room-detail',
        component: () => import('pages/RoomDetailPage.vue'),
        props: true,
        meta: { requiresPermission: 'room:read' },
      },
      {
        path: 'machines/:id',
        name: 'machine-detail',
        component: () => import('pages/MachineDetailPage.vue'),
        props: true,
      },
      {
        path: 'users',
        name: 'users',
        component: () => import('pages/UsersPage.vue'),
        meta: { requiresPermission: 'user:read' },
      },
      {
        path: 'groups',
        name: 'groups',
        component: () => import('pages/GroupsPage.vue'),
        meta: { requiresPermission: 'user:read' },
      },
      { path: 'account', name: 'account', component: () => import('pages/AccountPage.vue') },
    ],
  },
  {
    path: '/:catchAll(.*)*',
    component: () => import('pages/ErrorNotFound.vue'),
  },
];

export default routes;
