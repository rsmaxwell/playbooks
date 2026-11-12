multibranchPipelineJob('ledger-client-pipeline') {
    branchSources {
        git {
            id = 'ledger-client-pipeline'
            remote('ssh://git@ssh.github.com:443/rsmaxwell/ledger-client-pipeline.git')
            credentialsId('ledger-github-ssh')
        }
    }
}
