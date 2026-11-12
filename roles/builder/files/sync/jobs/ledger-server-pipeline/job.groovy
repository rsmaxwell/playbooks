multibranchPipelineJob('ledger-server-pipeline') {
    branchSources {
        git {
            id = 'ledger-server-pipeline'
            remote('ssh://git@ssh.github.com:443/rsmaxwell/ledger-server-pipeline.git')
            credentialsId('ledger-github-ssh')
        }
    }
}
