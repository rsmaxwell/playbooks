multibranchPipelineJob('mqtt-rpc-pipeline') {
    branchSources {
        git {
            id = 'mqtt-rpc-pipeline'
            remote('https://github.com/rsmaxwell/mqtt-rpc-pipeline.git')
        }
    }
}
