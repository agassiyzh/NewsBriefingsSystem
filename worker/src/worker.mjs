import workerModule from './index.js';

const { handleRequest } = workerModule;

export default {
  fetch(request, env) {
    return handleRequest(request, env);
  },
};
