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
        meta: { requiresAdmin: true },
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
