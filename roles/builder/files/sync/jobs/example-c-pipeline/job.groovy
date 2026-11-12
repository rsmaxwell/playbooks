multibranchPipelineJob('example-c-pipeline') {
    branchSources {
        git {
            id = 'example-c-pipeline'
            remote('https://github.com/rsmaxwell/example-c-pipeline.git')
        }
    }
}
