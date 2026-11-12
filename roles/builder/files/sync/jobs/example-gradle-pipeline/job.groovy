multibranchPipelineJob('example-gradle-pipeline') {
    branchSources {
        git {
            id = 'example-gradle-pipeline'
            remote('https://github.com/rsmaxwell/example-gradle-pipeline.git')
        }
    }
}
