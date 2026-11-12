multibranchPipelineJob('jansson-pipeline') {
    branchSources {
        git {
            id = 'jansson-pipeline'
            remote('https://github.com/rsmaxwell/jansson-pipeline.git')
        }
    }
}

