multibranchPipelineJob('example-cpp-pipeline') {
    branchSources {
        git {
            id = 'example-cpp-pipeline'
            remote('https://github.com/rsmaxwell/example-cpp-pipeline.git')
        }
    }
}
