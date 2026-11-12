multibranchPipelineJob('example-go-pipeline') {
    branchSources {
        git {
            id = 'example-go-pipeline'
            remote('https://github.com/rsmaxwell/example-go-pipeline.git')
        }
    }
}
