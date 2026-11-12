multibranchPipelineJob('example-maven-pipeline') {
    branchSources {
        git {
            id = 'example-maven-pipeline'
            remote('https://github.com/rsmaxwell/example-maven-pipeline.git')
        }
    }
}
