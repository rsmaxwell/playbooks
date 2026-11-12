#!/bin/bash

restServices="restServices"
redbackServices=${restServices}/redbackServices
loginService=${redbackServices}/loginService
loginEndpoint=${loginService}/logIn

userService=${redbackServices}/userService
createAdminUserEndpoint=${userService}/createAdminUser
createUserEndpoint=${userService}/createUser
getUsersEndpoint=${userService}/getUsers
getUserEndpoint=${userService}/getUser
updateMeEndpoint=${userService}/updateMe

roleManagementService=${redbackServices}/roleManagementService
allRolesEndpoint=${roleManagementService}/allRoles
getRoleEndpoint=${roleManagementService}/getRole
getEffectivelyAssignedRolesEndpoint=${roleManagementService}/getEffectivelyAssignedRoles
updateRoleUsersEndpoint=${roleManagementService}/updateRoleUsers
updateUserRolesEndpoint=${roleManagementService}/updateUserRoles

archivaServices=${restServices}/archivaServices
managedRepositoriesService=${archivaServices}/managedRepositoriesService
addManagedRepositoryEndpoint=${managedRepositoriesService}/addManagedRepository
getManagedRepositoriesEndpoint=${managedRepositoriesService}/getManagedRepositories
getManagedRepositoryEndpoint=${managedRepositoriesService}/getManagedRepository
deleteManagedRepositoryEndpoint=${managedRepositoriesService}/deleteManagedRepository

browseService=${archivaServices}/browseService
versionsListEndpoint=${browseService}/versionsList

archivaAdministrationService=${archivaServices}/archivaAdministrationService
enabledKnownContentConsumersEndpoint=${archivaAdministrationService}/enabledKnownContentConsumers
disabledKnownContentConsumerEndpoint=${archivaAdministrationService}/disabledKnownContentConsumer
getUiConfigurationEndpoint=${archivaAdministrationService}/getUiConfiguration
setUiConfigurationEndpoint=${archivaAdministrationService}/setUiConfiguration
