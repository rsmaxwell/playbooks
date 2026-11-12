multibranchPipelineJob('mqtt-rpc-go-pipeline') {
    branchSources {
        git {
            id = 'mqtt-rpc-go-pipeline'
            remote('https://github.com/rsmaxwell/mqtt-rpc-go-pipeline.git')
        }
    }
}
